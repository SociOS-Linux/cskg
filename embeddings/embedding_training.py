import click
from pathlib import Path
import shutil
from config import get_config
import json
import h5py
import os
import torch
from torchbiggraph.config import parse_config
from torchbiggraph.converters.importers import TSVEdgelistReader, convert_input_data
from torchbiggraph.train import train
from torchbiggraph.util import SubprocessInitializer, setup_logging
from torchbiggraph.converters.export_to_tsv import *


# Initializing libiomp5.dylib, but found libomp.dylib already initialized.
# solution: Allow repeat loading dynamic link library 
os.environ["KMP_DUPLICATE_LIB_OK"]="TRUE"


# CPU limitation: useless on linux server
# method 1 sometimes doesn't work
# torch.set_num_threads(1) # Sets the number of threads used for intraop parallelism on CPU.
# method 2
# OMP_NUM_THREADS='1'
# os.environ["OMP_NUM_THREADS"] = OMP_NUM_THREADS

def tsv_process(tsv_file,output_file): 
    output = open(output_file,'w')
    count = 0
    with open(tsv_file) as f:
        for line in f:
            content = line.split('\t')[:4]
            if content[1]!='node1':# ignore the first time 
                output.write(content[1]+'\t')
                output.write(content[2]+'\t')
                output.write(content[3]+'\n')

    output.close()

@click.command()
@click.option('-i','--input',help='Input KGTK file',required=True, metavar='')
@click.option('-o','--output',help='Output directory', required=True, metavar='')
@click.option('-d','--dimension',help='Dimension of the real space \
	the embedding live in [Default: 100]',default=100, type=int,metavar='')
@click.option('-s','--init_scale',help='Generating the initial \
	embedding with this standard deviation [Default: 0.01]',type=float,default=0.01, metavar='')
@click.option('-c','--comparator',help='Comparator types [Default:dot] Choice: dot|cos|l2|squared_l2 \
	',default='dot',type=click.Choice(['dot','cos','l2','squared_l2']),metavar='')
@click.option('-b','--bias',help='Whether use the bias choice [Default: False]',type=bool,default=False,metavar='')
@click.option('-e','--num_epochs',help='Training epoch numbers[Default: 100]',type=int,default=100,metavar='')
@click.option('-op','--operator',help='Operator types, it reflects which model that PBG uses. [Default:complex_diagonal] Choice: translation\
|linear|diagonal|complex_diagonal TransE=>translation, RESCAL=>linear, DistMult=>diagonal,\
ComplEx=>complex_diagonal',default='complex_diagonal',type=click.Choice(['translation','linear','diagonal','complex_diagonal']),metavar='')
@click.option('-ge','--global_emb',help='Whether use global embedding [Default: False]',type=bool,default=False,metavar='')
@click.option('-lf','--loss_fn',help='Type of loss function [Default: ranking] \
	Choice: ranking|logistic|softmax ',default='ranking',type=click.Choice(['ranking','logistic','softmax']),metavar='')
@click.option('-lr','--learning_rate',help='Learning rate [Default: 0.1]',type=float,default=0.1,metavar='')
@click.option('-rc','--regularization_coef',help='Regularization coefficient [Default: 1e-3]',type=float,default=1e-3,metavar='')
@click.option('-nn','--num_uniform_negs',help='Negative sampling number [Default: 1000]',type=int,default=1000,metavar='')
@click.option('-dr','--dynamic_relaitons',help='Whether use dynamic relations (when graphs with a \
	large number of relations)[Default: True]',type=bool,default=True,metavar='')
@click.option('-ef','--eval_fraction',help='Fraction of edges withheld from training and used \
	to track evaluation metrics during training [Default: 0.0]',type=float,default=0.0,metavar='')
@click.option('-nm','--num_machines',help='The number of machines for \
distributed training [Default: 1]',type=int,default=1,metavar='')
@click.option('-dm','--distributed_init_method',help='A URI defining how to synchronize all \
the workers of a distributed run[Default: None]',default=None,metavar='')
def main(**args):
    """
    Parameters setting and graph embedding
    """
    
    input_path = Path(args['input'])
    output_path = Path(args['output'])

    #if output_path is not empty, delete it
    try:  
        shutil.rmtree(output_path)
    except:pass


    #prepare the graph file
    tmp_tsv_path = Path('tmp') / input_path.name
    if tmp_tsv_path.exists():
        print('File is ready...')
    else:
        print('Generate the valid fromat for PBG training...')
        tsv_process(input_path,tmp_tsv_path)  
        print('File is ready...')

    # *********************************************
    # 1. DEFINE CONFIG  
    # *********************************************
    if args['num_machines']>1: # use disrtibuted mode:
        # A good default setting is to set num_machines to half the number of partitions
        num_partitions = args['num_machines']*2
    else:
        num_partitions = 1

    raw_config = get_config(**args)
    # print(raw_config)

    # **************************************************
    # 2. TRANSFORM GRAPH TO A BIGGRAPH-FRIENDLY FORMAT
    # **************************************************
    setup_logging()
    config = parse_config(raw_config)
    subprocess_init = SubprocessInitializer()
    input_edge_paths = [tmp_tsv_path] 

    convert_input_data(
        config.entities,
        config.relations,
        config.entity_path,
        config.edge_paths,
        input_edge_paths,
        TSVEdgelistReader(lhs_col=0, rel_col=1, rhs_col=2),
        dynamic_relations=config.dynamic_relations,
    )


    # ************************************************
    # 3. TRAIN THE EMBEDDINGS
    #*************************************************
    if args['num_machines'] == 1: # local
        train(config, subprocess_init=subprocess_init)
    else: # distributed 
        rank = input('Please give the rank of this machine:')
        train(config, subprocess_init=subprocess_init,rank=int(rank))


    # ************************************************
    # 4. GENERATE THE OUTPUT
    # ************************************************

    # config_dir = output_path / 'model/config.json'
    # print(config_dir)

    # f = open(config_dir)
    # config_dict = json.load(f)
    # f.close()

    # config = parse_config(config_dict)

    entities_output= output_path/ 'entities_output.tsv'
    relation_types_output = output_path/ 'relation_types_tf.tsv'

    with open(entities_output, "xt") as entities_tf, open(
        relation_types_output, "xt"
    ) as relation_types_tf:
        make_tsv(config, entities_tf, relation_types_tf)


if __name__ == "__main__":
    main()
    
    